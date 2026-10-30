// Equivalent BGR->RGB NCHW conversion; OpenCV performs vectorized channel conversion.
std::vector<float> imageToNchw(const cv::Mat &bgr, int size) {
  cv::Mat resized;
  if(bgr.cols!=size || bgr.rows!=size)
    cv::resize(bgr,resized,cv::Size(size,size),0,0,cv::INTER_LINEAR);
  else resized=bgr;
  std::vector<cv::Mat> channels;
  cv::split(resized,channels);
  if(channels.size()!=3 || resized.type()!=CV_8UC3)
    throw std::runtime_error("Expected 3-channel uint8 detector tensor source");
  size_t plane=static_cast<size_t>(size)*size;
  std::vector<float> tensor(3*plane);
  for(int c=0;c<3;++c) {
    cv::Mat target(size,size,CV_32F,tensor.data()+c*plane);
    channels[2-c].convertTo(target,CV_32F,1.0/255.0);
  }
  return tensor;
}

